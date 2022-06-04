# Import PyTorch
import torch
from torch import nn
from torch.autograd import Variable
# Import custom modules
from .loss import GaussianKLLoss, MaximumMeanDiscrepancyLoss

class Latent_module(nn.Module):
    def __init__(self, d_model, d_latent, variational_mode):

        super(Latent_module, self).__init__()

        self.variational_mode = variational_mode
        
        if self.variational_mode < 5:
            self.context_to_mu = nn.Linear(d_model, d_latent)
            self.context_to_logvar = nn.Linear(d_model, d_latent)
            self.z_to_context = nn.Linear(d_latent, d_model)

            self.kl_criterion = GaussianKLLoss()

        if self.variational_mode == 5:
            self.context_to_latent = nn.Linear(d_model, d_latent)
            self.latent_to_context = nn.Linear(d_latent, d_model)

            self.mmd_criterion = MaximumMeanDiscrepancyLoss()

        if self.variational_mode >= 6:
            self.latent_encoder = nn.Sequential(
                nn.Conv1d(in_channels=1024, out_channels=512, kernel_size=5, stride=3),
                nn.GELU(),
                nn.Conv1d(in_channels=512, out_channels=256, kernel_size=3, stride=3),
                nn.GELU(),
                nn.Conv1d(in_channels=256, out_channels=128, kernel_size=10, stride=1),
                nn.GELU(),
            )

            self.context_to_mu = nn.Linear(128, 128)
            self.context_to_logvar = nn.Linear(128, 128)

            self.latent_decoder = nn.Sequential(
                nn.ConvTranspose1d(in_channels=128, out_channels=256, kernel_size=10, stride=1),
                nn.GELU(),
                nn.ConvTranspose1d(in_channels=256, out_channels=512, kernel_size=5, stride=3),
                nn.GELU(),
                nn.ConvTranspose1d(in_channels=512, out_channels=1024, kernel_size=7, stride=3),
                nn.GELU(),
            )
            
            self.kl_criterion = GaussianKLLoss()
            self.mmd_criterion = MaximumMeanDiscrepancyLoss()

    def forward(self, encoder_out_src, encoder_out_trg=None):

    #===================================#
    #===SRC|TRG -> Z+Encoder_out(Sum)===#
    #===================================#

        if self.variational_mode == 1:
            src_mu = self.context_to_mu(encoder_out_src) # (token, batch, d_latent)
            src_logvar = self.context_to_logvar(encoder_out_src) # (token, batch, d_latent)

            trg_mu = self.context_to_mu(encoder_out_trg) # (token, batch, d_latent)
            trg_logvar = self.context_to_logvar(encoder_out_trg) # (token, batch, d_latent)

            dist_loss = self.kl_criterion(src_mu.mean(dim=1), src_logvar.mean(dim=1), 
                                          trg_mu.mean(dim=1), trg_logvar.mean(dim=1)) # 

            # Re-parameterization
            std = src_logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            z = eps.mul(std).add_(src_mu)

            resize_z = self.z_to_context(z)

            encoder_out_total = torch.add(encoder_out_src, resize_z)

    #===================================#
    #==SRC|TRG -> Z+Encoder_out(View)===#
    #===================================#

        if self.variational_mode == 2:
            batch_size = encoder_out_src.size(1)
            # Source sentence latent mapping
            src_mu = self.context_to_mu(encoder_out_src) # (token, batch, d_latent)
            src_logvar = self.context_to_logvar(encoder_out_src) # (token, batch, d_latent)

            trg_mu = self.context_to_mu(encoder_out_trg) # (token, batch, d_latent)
            trg_logvar = self.context_to_logvar(encoder_out_trg) # (token, batch, d_latent)

            mu1 = src_mu.view(batch_size, -1)
            logvar1 = src_logvar.view(batch_size, -1)
            mu2 = trg_mu.view(batch_size, -1)
            logvar2 = trg_logvar.view(batch_size, -1)

            numerator = logvar1.exp() + torch.pow(mu1 - mu2, 2)
            fraction = torch.div(numerator, (logvar2.exp()))

            dist_loss = 0.5 * torch.sum(logvar2 - logvar1 + fraction - 1, dim=0)
            dist_loss = dist_loss.mean()

            # Re-parameterization
            std = src_logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            z = eps.mul(std).add_(src_mu)

            resize_z = self.z_to_context(z)

            encoder_out_total = torch.add(encoder_out_src, resize_z)

    #===================================#
    #===========SRC -> Only Z===========#
    #===================================#

        if self.variational_mode == 3:
            # Source sentence latent mapping
            src_mu = self.context_to_mu(encoder_out_src) # (token, batch, d_latent)
            src_logvar = self.context_to_logvar(encoder_out_src) # (token, batch, d_latent)

            # KL Divergence
            mu = src_mu.view(encoder_out_src.size(1), -1)
            logvar = src_logvar.view(encoder_out_src.size(1), -1)
            dist_loss = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

            # Re-parameterization
            std = src_logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            z = eps.mul(std).add_(src_mu)

            encoder_out_total = self.z_to_context(z)

    #===================================#
    #=========SRC|TRG -> Only Z=========#
    #===================================#

        if self.variational_mode == 4:
            # Source sentence latent mapping
            src_mu = self.context_to_mu(encoder_out_src) # (token, batch, d_latent)
            src_logvar = self.context_to_logvar(encoder_out_src) # (token, batch, d_latent)

            trg_mu = self.context_to_mu(encoder_out_trg) # (token, batch, d_latent)
            trg_logvar = self.context_to_logvar(encoder_out_trg) # (token, batch, d_latent)

            dist_loss = self.kl_criterion(src_mu, src_logvar, trg_mu, trg_logvar) # 

            # Re-parameterization
            std = src_logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            z = eps.mul(std).add_(src_mu)

            resize_z = self.z_to_context(z)

            # Re-parameterization
            std = src_logvar.mul(0.5).exp_()
            eps = Variable(std.data.new(std.size()).normal_())
            z = eps.mul(std).add_(src_mu)

            encoder_out_total = self.z_to_context(z)

    #===================================#
    #================WAE================#
    #===================================#

        if self.variational_mode == 5:
            # Source sentence latent mapping
            src_latent = self.context_to_latent(encoder_out_src) # (token, batch, d_latent)
            trg_latent = self.context_to_latent(encoder_out_trg) # (token, batch, d_latent)

            dist_loss = self.mmd_criterion(src_latent.mean(dim=1), trg_latent.mean(dim=1), 100) # z_var is 2 now

            #
            src_latent = self.latent_to_context(src_latent)

            encoder_out_total = torch.add(encoder_out_src, src_latent)

    #===================================#
    #==============CNN+VAE==============#
    #===================================#

        if self.variational_mode == 6:
            # Source sentence latent mapping
            encoder_out_src = encoder_out_src.transpose(1,2)
            encoder_out_trg = encoder_out_trg.transpose(1,2)

            src_latent = self.latent_encoder(encoder_out_src)
            trg_latent = self.latent_encoder(encoder_out_trg)

            src_mu = self.context_to_mu(src_latent.squeeze(2)) # (token, batch, d_latent)
            src_logvar = self.context_to_logvar(src_latent.squeeze(2)) # (token, batch, d_latent)

            trg_mu = self.context_to_mu(trg_latent.squeeze(2)) # (token, batch, d_latent)
            trg_logvar = self.context_to_logvar(trg_latent.squeeze(2)) # (token, batch, d_latent)
            
            dist_loss = self.kl_criterion(src_mu, src_logvar, trg_mu, trg_logvar) # 

            #
            src_latent = self.latent_decoder(src_latent)

            src_latent = src_latent.transpose(1,2)
            encoder_out_src = encoder_out_src.transpose(1,2)

            encoder_out_total = torch.add(encoder_out_src, src_latent)


    #===================================#
    #==============CNN+WAE==============#
    #===================================#

        if self.variational_mode == 7:
            # Source sentence latent mapping
            encoder_out_src = encoder_out_src.transpose(1,2)
            encoder_out_trg = encoder_out_trg.transpose(1,2)

            src_latent = self.latent_encoder(encoder_out_src)
            trg_latent = self.latent_encoder(encoder_out_trg)

            dist_loss = self.mmd_criterion(src_latent.squeeze(2), trg_latent.squeeze(2), 100) # z_var is 2 now

            #
            src_latent = self.latent_decoder(src_latent)

            src_latent = src_latent.transpose(1,2)
            encoder_out_src = encoder_out_src.transpose(1,2)

            encoder_out_total = torch.add(encoder_out_src, src_latent)

        return encoder_out_total, dist_loss